"""AD-1185: the config-profile contract, and the ways it could be theatre.

The load-bearing test in this module is
:func:`test_a_misspelled_nested_key_raises_rather_than_being_ignored`.
``SystemConfig.model_config`` is empty, so Pydantic v2's default
``extra="ignore"`` applies at every level: a profile that claims to arm
``browser_tool.action_dispatch_enabled`` but spells it
``action_dispatch_enable`` parses cleanly and ships the feature OFF. Without
the loader's key pre-validation every other assertion here still passes and
the contract proves nothing, so that test is written first and its companion
:func:`test_pydantic_alone_would_have_ignored_the_misspelled_key` pins the
hazard itself -- if Pydantic ever starts rejecting unknown keys, that test
fails and this whole layer can be reconsidered.

**A skipped smoke is a failed smoke.**
:func:`test_supported_profile_boots_and_reads_a_file` is the CI boot #1121
asks for. A skip count moving is invisible in a suite's ``passed`` total, so
``scripts/check_config_profiles.py`` resolves that test's node id by AST from
the manifest and fails if it is renamed, deleted, or given a
skip/skipif/xfail marker.

**Injection tests copy rather than mutate.** The prompt's ``.mutbak``-and-
restore pattern exists to guarantee an injected row never survives the test.
Copying the manifest into ``tmp_path`` and pointing the checker at the copy is
strictly stronger: there is no window in which the committed file is wrong,
even if the process is killed mid-test. Each injection test additionally
asserts the committed manifest's bytes are unchanged, so the guarantee is
verified rather than assumed.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import SystemConfig, load_config
from probos.config_profiles import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_PROFILE_DIR,
    FORBIDDEN_PROFILE_IDS,
    PROFILE_ARMS,
    PROFILE_IDS,
    UNRESOLVED,
    ProfileConflictError,
    ProfileError,
    ProfileRule,
    discover_profile_ids,
    iter_rule_violations,
    load_profile,
    load_profile_document,
    override_paths,
    read_manifest_rules,
    resolve_flag,
    validate_override_keys,
)
from probos.runtime import ProbOSRuntime

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_SOURCE = (_REPO_ROOT / "src" / "probos" / "config_profiles.py").read_text(
    encoding="utf-8"
)
_SMOKE_NODE_ID = (
    "tests/test_ad1185_config_profiles.py::test_supported_profile_boots_and_reads_a_file"
)
_ENV_DEPENDENT_DEFAULTS = ("PROBOS_NATS_ENABLED", "PROBOS_LLM_URL")


def _load_checker():
    """Import ``scripts/check_config_profiles.py`` by path.

    ``scripts/`` is not a package, so this mirrors how the gate invokes it
    rather than inventing an import path that only tests use.
    """
    path = _REPO_ROOT / "scripts" / "check_config_profiles.py"
    spec = importlib.util.spec_from_file_location("_ad1185_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _canonical_sha(config: SystemConfig) -> str:
    """SHA-256 over the canonicalised JSON dump.

    Deliberately not compared against a hard-coded constant: a legitimate
    default change would then require editing a magic string with no diff
    explaining it. The assertion is always over a PAIR computed in the same
    process.
    """
    payload = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_profile(directory: Path, profile_id: str, document: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile_id}.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


_FRESH_PROCESS_PROBE = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from probos.config import SystemConfig
from probos.config_profiles import load_profile

def canon(config):
    payload = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

defaults = SystemConfig()
print(json.dumps({
    "profile": canon(load_profile("minimal")),
    "default": canon(defaults),
    "nats": defaults.nats.enabled,
    "llm": defaults.cognitive.llm_base_url,
}))
"""


def _fresh_process_shas(env_overrides: dict[str, str | None]) -> dict[str, Any]:
    """Compute both shas in a NEW interpreter under a chosen environment.

    ``SystemConfig.nats`` is a shared instance built at import time, so an
    in-test ``monkeypatch`` cannot change it (see
    :func:`test_the_nats_dependence_is_import_time_not_construction_time`).
    Only a fresh process can establish environment independence rather than
    merely appear to.
    """
    env = dict(os.environ)
    env.setdefault("HF_HUB_OFFLINE", "1")
    for name, value in env_overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    completed = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS_PROBE, str(_REPO_ROOT / "src")],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _manifest_copy(tmp_path: Path) -> Path:
    target = tmp_path / "config-profiles.yaml"
    target.write_bytes(DEFAULT_MANIFEST_PATH.read_bytes())
    return target


def _mutate_manifest(tmp_path: Path, mutate) -> Path:
    path = _manifest_copy(tmp_path)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _check_with(manifest: Path):
    return checker.check(
        manifest_path=manifest,
        profile_dir=DEFAULT_PROFILE_DIR,
        repo_root=_REPO_ROOT,
        conftest=_REPO_ROOT / "tests" / "conftest.py",
        config_module=_REPO_ROOT / "src" / "probos" / "config.py",
    )


# --------------------------------------------------------------------------
# 1. Key pre-validation -- without this the whole contract is unfalsifiable.
# --------------------------------------------------------------------------


def test_pydantic_alone_would_have_ignored_the_misspelled_key() -> None:
    """The hazard is real, and this test is what proves the loader earns its keep."""
    assert SystemConfig.model_config == {}
    config = SystemConfig.model_validate({"nats": {"enabld": True}})
    assert config.nats.enabled is False
    assert not hasattr(config, "enabld")


def test_a_misspelled_nested_key_raises_rather_than_being_ignored(
    tmp_path: Path,
) -> None:
    _write_profile(
        tmp_path,
        "typo",
        {
            "profile": {
                "id": "typo",
                "version": 1,
                "description": "a typo",
                "arm": "experiment",
            },
            "overrides": {"nats": {"enabld": True}},
        },
    )
    with pytest.raises(ProfileError) as excinfo:
        load_profile_document("typo", tmp_path)
    assert "nats.enabld" in str(excinfo.value)


def test_the_key_error_names_the_closest_valid_sibling() -> None:
    errors = validate_override_keys({"nats": {"enabld": True}})
    assert len(errors) == 1
    assert "'enabled'" in errors[0]


def test_all_bad_keys_are_accumulated_into_one_error() -> None:
    errors = validate_override_keys(
        {
            "nats": {"enabld": True, "urll": "x"},
            "memory": {"hybrid_recall_enabld": True},
        }
    )
    assert len(errors) == 3
    joined = " ".join(errors)
    assert "nats.enabld" in joined
    assert "nats.urll" in joined
    assert "memory.hybrid_recall_enabld" in joined


def test_an_unknown_top_level_section_is_rejected() -> None:
    errors = validate_override_keys({"typo_section": {"x": 1}})
    assert len(errors) == 1
    assert "typo_section" in errors[0]


def test_a_correctly_spelled_key_passes_pre_validation() -> None:
    assert validate_override_keys({"nats": {"enabled": True}}) == []


def test_a_deeply_nested_correct_key_passes() -> None:
    assert validate_override_keys(
        {"security": {"memory": {"enforce_store": True}}}
    ) == []


def test_a_deeply_nested_typo_is_caught() -> None:
    errors = validate_override_keys(
        {"security": {"memory": {"enforce_stor": True}}}
    )
    assert len(errors) == 1
    assert "security.memory.enforce_stor" in errors[0]


def test_a_non_string_key_is_rejected() -> None:
    errors = validate_override_keys({7: {"enabled": True}})
    assert len(errors) == 1
    assert "int" in errors[0]


def test_override_paths_lists_dotted_leaves() -> None:
    paths = override_paths(
        {"approval_inbox": {"enabled": True}, "memory": {"hybrid_recall_enabled": True}}
    )
    assert paths == ["approval_inbox.enabled", "memory.hybrid_recall_enabled"]


def test_a_mapping_valued_field_is_not_walked_as_a_model() -> None:
    """``dict[str, X]`` fields hold operator-chosen keys, not model fields."""
    errors = validate_override_keys(
        {"security_infra": {"egress_allowlist": ["example.com"]}}
    )
    assert errors == []


# --------------------------------------------------------------------------
# 1b. Models reached through a container are still schema.
#
# ``SystemConfig`` reaches a model only through a ``list[...]`` or
# ``dict[str, ...]`` in six places, and Pydantic drops an unknown key inside
# one exactly as silently as a top-level typo. Each pin below was measured
# ACCEPTED before the walk descended containers, which is the whole point:
# pre-validation that stops at the container makes the profile contract
# unfalsifiable for everything underneath it.
#
# The split these tests fix in place: in ``dict[str, Model]`` the *key* is
# operator data (a department name) and must stay free, while the fields
# *beneath* it are schema and must resolve. Both directions are pinned,
# because getting either wrong is a defect.
# --------------------------------------------------------------------------


def test_an_unknown_field_inside_a_dict_of_models_is_rejected() -> None:
    """The reviewer's repro: accepted before, and silently dropped by Pydantic."""
    errors = validate_override_keys(
        {"dept_profiles": {"profiles": {"ops": {"nonexistent_field": 1}}}}
    )
    assert len(errors) == 1
    assert "dept_profiles.profiles.ops.nonexistent_field" in errors[0]


def test_an_arbitrary_dict_key_is_data_and_stays_legal() -> None:
    """Department names are operator-chosen; only what sits beneath them is schema."""
    assert (
        validate_override_keys(
            {"dept_profiles": {"profiles": {"zzz-invented-dept": {"recall_depth": 7}}}}
        )
        == []
    )


def test_a_typo_beneath_an_arbitrary_dict_key_still_names_its_sibling() -> None:
    errors = validate_override_keys(
        {"dept_profiles": {"profiles": {"ops": {"recall_dept": 7}}}}
    )
    assert len(errors) == 1
    assert "'recall_depth'" in errors[0]


def test_an_unknown_field_inside_a_list_element_is_rejected() -> None:
    """``mcp.servers[0].bogus`` -- accepted before, and dropped by Pydantic."""
    errors = validate_override_keys({"mcp": {"servers": [{"bogus": 1}]}})
    assert len(errors) == 1
    assert "mcp.servers[0].bogus" in errors[0]


def test_a_valid_list_element_passes() -> None:
    assert (
        validate_override_keys(
            {"mcp": {"servers": [{"name": "x", "type": "stdio", "command": "echo"}]}}
        )
        == []
    )


def test_addressing_a_sequence_field_by_index_key_is_rejected() -> None:
    """A list is written as a YAML list. There is no index-as-key override form."""
    errors = validate_override_keys({"mcp": {"servers": {"0": {"name": "x"}}}})
    assert len(errors) == 1
    assert "sequence field" in errors[0]
    assert "YAML list" in errors[0]


def test_a_model_two_containers_deep_is_still_walked() -> None:
    """``dict[str, list[Model]]``: data key, then index, then schema."""
    errors = validate_override_keys(
        {
            "proactive_cognitive": {
                "duty_schedule": {"schedules": {"engineering": [{"nope": 1}]}}
            }
        }
    )
    assert len(errors) == 1
    assert (
        "proactive_cognitive.duty_schedule.schedules.engineering[0].nope" in errors[0]
    )


def test_a_validation_alias_is_accepted_because_pydantic_honours_it() -> None:
    """``model_config == {}`` means no ``populate_by_name``, so aliases are the key.

    ``SensoriumConfig.warning_chars`` carries
    ``AliasChoices('warning_chars', 'token_budget_warning')`` and Pydantic sets
    the field from either. Resolving against ``model_fields`` alone refused the
    alias -- a legitimate config rejected, the mirror image of the bug above.
    """
    assert validate_override_keys({"sensorium": {"token_budget_warning": 4242}}) == []
    assert validate_override_keys({"sensorium": {"warning_chars": 4242}}) == []
    assert SystemConfig.model_validate(
        {"sensorium": {"token_budget_warning": 4242}}
    ).sensorium.warning_chars == 4242


# --------------------------------------------------------------------------
# 2. `minimal` byte identity -- the ablation control arm.
# --------------------------------------------------------------------------


def test_minimal_is_byte_identical_to_the_model_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With every environment-dependent default deleted, not merely conftest's value."""
    for name in _ENV_DEPENDENT_DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    assert _canonical_sha(load_profile("minimal")) == _canonical_sha(SystemConfig())


def test_minimal_and_the_defaults_move_together_in_a_fresh_process_with_nats_true() -> None:
    """Identity is over the PAIR, computed together -- never a fixed constant."""
    result = _fresh_process_shas({"PROBOS_NATS_ENABLED": "true"})
    assert result["profile"] == result["default"]
    # Not vacuous: prove the variable actually took effect in that process.
    assert result["nats"] is True


def test_minimal_and_the_defaults_move_together_in_a_fresh_process_with_llm_url() -> None:
    """PROBOS_LLM_URL is a second environment-dependent default (model_validator)."""
    url = "http://probe.invalid:9999"
    result = _fresh_process_shas({"PROBOS_LLM_URL": url})
    assert result["profile"] == result["default"]
    assert result["llm"] == url


def test_minimal_matches_the_defaults_in_a_fresh_process_with_the_env_deleted() -> None:
    result = _fresh_process_shas({"PROBOS_NATS_ENABLED": None, "PROBOS_LLM_URL": None})
    assert result["profile"] == result["default"]
    assert result["nats"] is False


def test_the_environment_really_does_move_the_default_dump() -> None:
    """Otherwise every identity assertion above could pass vacuously."""
    off = _fresh_process_shas({"PROBOS_NATS_ENABLED": "false", "PROBOS_LLM_URL": None})
    on = _fresh_process_shas({"PROBOS_NATS_ENABLED": "true", "PROBOS_LLM_URL": None})
    assert off["default"] != on["default"]


def test_the_nats_dependence_is_import_time_not_construction_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-09-02, and the reason the tests above spawn a process.

    ``SystemConfig.nats`` is declared ``nats: NatsConfig = NatsConfig()`` -- a
    shared instance built once at module import. ``validate_default=True``
    therefore reads ``PROBOS_NATS_ENABLED`` at IMPORT, so a ``monkeypatch``
    inside a test cannot move ``SystemConfig()`` no matter what it sets. A
    byte-identity test that relies on in-test ``delenv`` for environment
    independence is asserting nothing about the environment.
    """
    from probos.config import NatsConfig

    baseline = SystemConfig().nats.enabled
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    assert SystemConfig().nats.enabled is baseline
    assert NatsConfig().enabled is True


def test_minimal_carries_an_empty_override_delta() -> None:
    document = load_profile_document("minimal")
    assert document.overrides == {}
    assert document.arm == "control"


def test_minimal_arms_no_flag() -> None:
    assert override_paths(load_profile_document("minimal").overrides) == []


# --------------------------------------------------------------------------
# 3. The shipped profiles.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_every_registered_profile_loads(profile_id: str) -> None:
    assert isinstance(load_profile(profile_id), SystemConfig)


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_every_registered_profile_declares_a_known_arm(profile_id: str) -> None:
    assert load_profile_document(profile_id).arm in PROFILE_ARMS


def test_the_profile_directory_matches_the_registered_ids() -> None:
    assert discover_profile_ids(DEFAULT_PROFILE_DIR) == PROFILE_IDS


def test_supported_arms_exactly_the_four_reviewed_flags() -> None:
    paths = override_paths(load_profile_document("supported").overrides)
    assert paths == [
        "approval_inbox.enabled",
        "memory.hybrid_recall_enabled",
        "security.memory.enforce_provenance",
        "security.memory.enforce_store",
    ]


def test_supported_resolves_those_flags_on() -> None:
    config = load_profile("supported")
    assert config.approval_inbox.enabled is True
    assert config.memory.hybrid_recall_enabled is True
    assert config.security.memory.enforce_store is True
    assert config.security.memory.enforce_provenance is True


def test_supported_arms_no_optional_integration_flag() -> None:
    """Admission rule 3: the smoke is offline, so no external dependency may be armed."""
    config = load_profile("supported")
    assert config.nats.enabled is False
    assert config.channels.discord.enabled is False
    assert config.execution.enabled is False
    assert config.browser_tool.enabled is False
    assert config.federation.enabled is False


def test_supported_is_not_a_copy_of_the_operator_config() -> None:
    """config/system.yaml is the reference vessel, not the product contract."""
    vessel = override_paths(
        yaml.safe_load((_REPO_ROOT / "config" / "system.yaml").read_text("utf-8"))
    )
    supported = override_paths(load_profile_document("supported").overrides)
    assert set(supported) != set(vessel)
    assert len(supported) < len(vessel)


def test_an_experimental_profile_ships() -> None:
    experiments = [
        profile_id
        for profile_id in PROFILE_IDS
        if load_profile_document(profile_id).arm == "experiment"
    ]
    assert experiments == ["experimental-approval-standing-rules"]


def test_the_experimental_profile_satisfies_its_requires_edge() -> None:
    config = load_profile("experimental-approval-standing-rules")
    assert config.approval_inbox.standing_rules_enabled is True
    assert config.approval_inbox.enabled is True


def test_no_shipped_profile_arms_everything() -> None:
    """An everything-on profile is unsafe by construction and must not exist."""
    off_flags = set(checker.default_false_flags())
    for profile_id in PROFILE_IDS:
        armed = set(override_paths(load_profile_document(profile_id).overrides))
        assert len(armed) < len(off_flags) / 2


# --------------------------------------------------------------------------
# 4. Profile file shape.
# --------------------------------------------------------------------------


def _valid_document(profile_id: str = "probe") -> dict[str, Any]:
    return {
        "profile": {
            "id": profile_id,
            "version": 1,
            "description": "probe",
            "arm": "experiment",
        },
        "overrides": {},
    }


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        (lambda d: d.pop("overrides"), "missing required top-level key"),
        (lambda d: d.pop("profile"), "missing required top-level key"),
        (lambda d: d.update(extra=1), "unexpected top-level key"),
        (lambda d: d["profile"].pop("arm"), "'arm'"),
        (lambda d: d["profile"].update(nope=1), "unexpected key(s) in 'profile:'"),
        (lambda d: d["profile"].update(id="other"), "is filed as"),
        (lambda d: d["profile"].update(arm="banana"), "'arm' must be one of"),
        (lambda d: d["profile"].update(version=0), "'version' must be an integer"),
        (lambda d: d["profile"].update(version=True), "'version' must be an integer"),
        (lambda d: d["profile"].update(description="  "), "'description' must be"),
        (lambda d: d.update(overrides=None), "empty delta"),
        (lambda d: d.update(overrides=[1]), "'overrides:' must be a mapping"),
    ],
)
def test_a_malformed_profile_is_refused(
    tmp_path: Path, mutation, fragment: str
) -> None:
    document = _valid_document()
    mutation(document)
    _write_profile(tmp_path, "probe", document)
    with pytest.raises(ProfileError) as excinfo:
        load_profile_document("probe", tmp_path)
    assert fragment in str(excinfo.value)


def test_an_unknown_profile_id_names_the_available_ones(tmp_path: Path) -> None:
    with pytest.raises(ProfileError) as excinfo:
        load_profile_document("nope", tmp_path)
    assert "no config profile 'nope'" in str(excinfo.value)


def test_a_malformed_profile_id_is_refused() -> None:
    with pytest.raises(ProfileError, match="not a valid profile id"):
        load_profile_document("Not_A_Profile")


def test_an_empty_profile_id_is_refused() -> None:
    with pytest.raises(ProfileError, match="non-empty string"):
        load_profile_document("")


def test_a_profile_file_that_is_not_yaml_mapping_is_refused(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "probe.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="must be a mapping"):
        load_profile_document("probe", tmp_path)


# --------------------------------------------------------------------------
# 5. Disjointness from the extension-profile vocabulary (D6).
# --------------------------------------------------------------------------


@pytest.mark.parametrize("profile_id", sorted(FORBIDDEN_PROFILE_IDS))
def test_extension_profile_names_are_refused_as_config_profiles(
    profile_id: str,
) -> None:
    with pytest.raises(ProfileError, match="reserved by probos.extensions.profiles"):
        load_profile_document(profile_id)


def test_the_loader_never_imports_the_extension_profile_module() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(_MODULE_SOURCE)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("extensions" in name for name in imported), sorted(imported)


def test_the_loader_never_reads_extensions_default_profile() -> None:
    """AST only.

    A substring scan cannot tell a comment that documents the name collision
    from code that reads the field, and this module's own comments discuss
    ``ExtensionsConfig.default_profile`` on purpose. Comments are absent from
    the AST, so attribute access and ``getattr``-style string constants are the
    two shapes a real read could take.
    """
    tree = ast.parse(_MODULE_SOURCE)
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "default_profile" not in attributes
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "default_profile" not in constants


def test_the_two_profile_directories_are_distinct() -> None:
    assert DEFAULT_PROFILE_DIR.name == "profiles"
    assert DEFAULT_PROFILE_DIR.parent.name == "config"
    assert not (DEFAULT_PROFILE_DIR / "developer.yaml").exists()
    assert not (DEFAULT_PROFILE_DIR / "full.yaml").exists()


# --------------------------------------------------------------------------
# 6. requires / conflicts_with, enforced at parse (D3).
# --------------------------------------------------------------------------


def test_a_conflicting_profile_raises_at_parse(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "probe",
        {
            "profile": {
                "id": "probe",
                "version": 1,
                "description": "deliberate conflict",
                "arm": "experiment",
            },
            "overrides": {
                "social_verification": {"expose_episode_content": True},
                "security": {"memory": {"enforce_leak_guard": True}},
            },
        },
    )
    with pytest.raises(ProfileConflictError) as excinfo:
        load_profile("probe", profile_dir=tmp_path)
    assert "conflicts with" in str(excinfo.value)


def test_a_requires_violation_raises_at_parse(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "probe",
        {
            "profile": {
                "id": "probe",
                "version": 1,
                "description": "standing rules without parking",
                "arm": "experiment",
            },
            "overrides": {"approval_inbox": {"standing_rules_enabled": True}},
        },
    )
    with pytest.raises(ProfileConflictError, match="requires approval_inbox.enabled"):
        load_profile("probe", profile_dir=tmp_path)


def test_a_conflicting_profile_never_becomes_a_system_config(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "probe",
        {
            "profile": {
                "id": "probe",
                "version": 1,
                "description": "conflict",
                "arm": "experiment",
            },
            "overrides": {"approval_inbox": {"standing_rules_enabled": True}},
        },
    )
    result: Any = "not reassigned"
    try:
        result = load_profile("probe", profile_dir=tmp_path)
    except ProfileConflictError:
        pass
    assert result == "not reassigned"


def test_conflict_error_is_a_profile_error() -> None:
    assert issubclass(ProfileConflictError, ProfileError)


def test_an_unarmed_subject_constrains_nothing() -> None:
    rule = ProfileRule(path="nats.enabled", requires=("federation.enabled",))
    assert iter_rule_violations(SystemConfig(), [rule]) == []


def test_an_armed_subject_with_a_missing_dependency_is_a_violation() -> None:
    # Deliberately not nats.enabled: conftest forces PROBOS_NATS_ENABLED=false
    # and the field validator overrides an explicit True, so that flag cannot
    # be armed anywhere in this suite.
    config = SystemConfig.model_validate({"federation": {"enabled": True}})
    assert config.federation.enabled is True
    rule = ProfileRule(path="federation.enabled", requires=("federation.tls.enabled",))
    violations = iter_rule_violations(config, [rule])
    assert len(violations) == 1
    assert "requires federation.tls.enabled" in violations[0]


def test_an_armed_subject_with_a_live_conflict_is_a_violation() -> None:
    config = SystemConfig.model_validate(
        {"federation": {"enabled": True, "tls": {"enabled": True}}}
    )
    rule = ProfileRule(
        path="federation.enabled", conflicts_with=("federation.tls.enabled",)
    )
    violations = iter_rule_violations(config, [rule])
    assert len(violations) == 1
    assert "but both are on" in violations[0]


def test_a_rule_naming_an_absent_path_is_reported_not_ignored() -> None:
    rule = ProfileRule(path="nats.no_such_flag")
    violations = iter_rule_violations(SystemConfig(), [rule])
    assert len(violations) == 1
    assert "broken manifest row" in violations[0]


def test_resolve_flag_distinguishes_absent_from_off() -> None:
    defaults = SystemConfig()
    assert resolve_flag(defaults, "nats.enabled") is False
    assert resolve_flag(defaults, "nats.no_such_flag") is UNRESOLVED


def test_no_declared_rule_fires_against_the_model_defaults() -> None:
    assert iter_rule_violations(SystemConfig(), read_manifest_rules()) == []


@pytest.mark.parametrize(
    "relative", ["config/system.yaml", "config/node-1.yaml", "config/node-2.yaml"]
)
def test_no_declared_rule_fires_against_a_tracked_config(relative: str) -> None:
    config = load_config(_REPO_ROOT / relative)
    assert iter_rule_violations(config, read_manifest_rules()) == []


def test_the_tracked_operator_config_actually_exercises_a_rule() -> None:
    """Otherwise the four zero-violation proofs above could all be vacuous."""
    config = load_config(_REPO_ROOT / "config" / "system.yaml")
    subjects = {
        rule.path
        for rule in read_manifest_rules()
        if (rule.requires or rule.conflicts_with)
        and resolve_flag(config, rule.path) is True
    }
    assert subjects, "no declared rule has an armed subject in config/system.yaml"


def test_a_missing_manifest_is_fatal_rather_than_silently_ruleless(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProfileError, match="conflicts cannot be enforced"):
        read_manifest_rules(tmp_path / "absent.yaml")


def test_a_manifest_without_a_flags_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text("schema_version: 1\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="no 'flags:' list"):
        read_manifest_rules(path)


def test_a_manifest_rule_field_of_the_wrong_type_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text(
        yaml.safe_dump({"flags": [{"path": "nats.enabled", "requires": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ProfileError, match="must be a list of"):
        read_manifest_rules(path)


# --------------------------------------------------------------------------
# 7. The checker, in both directions.
# --------------------------------------------------------------------------


def test_the_checker_passes_on_the_committed_tree() -> None:
    result = _check_with(DEFAULT_MANIFEST_PATH)
    assert result.errors == []


def test_the_checker_cli_exits_zero() -> None:
    assert checker.main(["--check"]) == 0


def test_the_report_names_all_four_config_evaluations() -> None:
    evaluations = _check_with(DEFAULT_MANIFEST_PATH).report["rule_evaluations"]
    assert set(evaluations) == {
        "SystemConfig()",
        "config/system.yaml",
        "config/node-1.yaml",
        "config/node-2.yaml",
    }
    for detail in evaluations.values():
        assert detail["violations"] == []
        assert detail["rules_evaluated"] > 0


def test_the_census_covers_every_default_off_flag() -> None:
    report = _check_with(DEFAULT_MANIFEST_PATH).report
    assert report["classified"] + report["frozen_unclassified"] == (
        report["default_false_flags"]
    )


def test_the_measured_census_matches_the_manifest_header() -> None:
    document = yaml.safe_load(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert document["census"]["default_false"] == len(checker.default_false_flags())


def _assert_committed_manifest_untouched(before: bytes) -> None:
    assert DEFAULT_MANIFEST_PATH.read_bytes() == before


def test_a_row_naming_an_absent_path_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path,
            lambda d: d["flags"].append(
                {
                    "path": "nats.no_such_flag",
                    "kind": "product-feature",
                    "profiles": [],
                    "evidence_to_promote": "injected",
                    "external_dependency": None,
                    "requires": [],
                    "conflicts_with": [],
                }
            ),
        )
        errors = _check_with(manifest).errors
        assert any("nats.no_such_flag" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_new_default_off_flag_in_neither_list_fails(tmp_path: Path) -> None:
    """Simulated by removing a frozen row: the live model then has an unlisted flag."""
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["unclassified_flags"].pop(0)
        )
        errors = _check_with(manifest).errors
        assert any("in neither flags:" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_flag_in_both_lists_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["unclassified_flags"].append("nats.enabled")
        )
        errors = _check_with(manifest).errors
        assert any("both classified and frozen" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_stale_frozen_row_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["unclassified_flags"].append("gone.forever")
        )
        errors = _check_with(manifest).errors
        assert any("no longer a default-False flag" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


@pytest.mark.parametrize("key", ["owner", "rationale", "review_by"])
def test_a_blank_review_field_fails(tmp_path: Path, key: str) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(tmp_path, lambda d: d["review"].update({key: "  "}))
        errors = _check_with(manifest).errors
        assert any(f"review.{key} is blank" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_seventh_kind_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["flags"][0].update({"kind": "nice-to-have"})
        )
        errors = _check_with(manifest).errors
        assert any("nice-to-have" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_an_optional_integration_without_an_external_dependency_fails(
    tmp_path: Path,
) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        for row in document["flags"]:
            if row["path"] == "nats.enabled":
                row["external_dependency"] = None

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any("names no external_dependency" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_blank_evidence_to_promote_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["flags"][0].update({"evidence_to_promote": ""})
        )
        errors = _check_with(manifest).errors
        assert any("blank evidence_to_promote" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_an_unexplained_conflict_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        for row in document["flags"]:
            if row.get("conflicts_with"):
                row.pop("conflict_rationale", None)

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any("no conflict_rationale" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_duplicate_row_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path, lambda d: d["flags"].append(dict(d["flags"][0]))
        )
        errors = _check_with(manifest).errors
        assert any("classified twice" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_profiles_claim_the_profile_does_not_make_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        for row in document["flags"]:
            if row["path"] == "os_activity.enabled":
                row["profiles"] = ["supported"]

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any("but that profile's overrides do not" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_missing_smoke_node_id_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()
    try:
        manifest = _mutate_manifest(
            tmp_path,
            lambda d: d.update(
                smoke_test_node_id=(
                    "tests/test_ad1185_config_profiles.py::test_renamed_away"
                )
            ),
        )
        errors = _check_with(manifest).errors
        assert any("renamed or deleted" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


# --------------------------------------------------------------------------
# 8. CI divergences, both directions (D5).
# --------------------------------------------------------------------------


def test_every_conftest_setdefault_pair_is_read_by_ast() -> None:
    pairs = checker._conftest_setdefaults(_REPO_ROOT / "tests" / "conftest.py")
    assert pairs["PROBOS_NATS_ENABLED"] == "false"
    assert pairs["HF_HUB_OFFLINE"] == "1"


def test_env_reads_reaching_defaults_are_classified_by_validator_kind() -> None:
    reaching = checker.env_reads_reaching_defaults(
        _REPO_ROOT / "src" / "probos" / "config.py"
    )
    assert reaching == {
        "PROBOS_NATS_ENABLED": "config-field-validator",
        "PROBOS_LLM_URL": "model-validator",
    }


def test_xdg_data_home_is_not_treated_as_reaching_a_default() -> None:
    """It is read inside a plain function, so it cannot reach ``model_dump()``."""
    reaching = checker.env_reads_reaching_defaults(
        _REPO_ROOT / "src" / "probos" / "config.py"
    )
    assert "XDG_DATA_HOME" not in reaching


def test_every_reaching_env_read_is_declared() -> None:
    document = yaml.safe_load(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    declared = {row["env_var"] for row in document["ci_divergences"]}
    reaching = checker.env_reads_reaching_defaults(
        _REPO_ROOT / "src" / "probos" / "config.py"
    )
    assert set(reaching) <= declared


def test_the_hugging_face_divergence_claims_no_config_path() -> None:
    document = yaml.safe_load(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    row = next(
        item
        for item in document["ci_divergences"]
        if item["env_var"] == "HF_HUB_OFFLINE"
    )
    assert row["mechanism"] == "third-party-env"
    assert row["config_path"] is None


def test_an_undeclared_environment_dependent_default_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        document["ci_divergences"] = [
            row
            for row in document["ci_divergences"]
            if row["env_var"] != "PROBOS_LLM_URL"
        ]

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any(
            "PROBOS_LLM_URL" in error and "no ci_divergences row" in error
            for error in errors
        )
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_stale_conftest_declaration_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        for row in document["ci_divergences"]:
            if row["env_var"] == "PROBOS_NATS_ENABLED":
                row["set_to"] = "true"

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any("but the row declares" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


def test_a_wrong_mechanism_fails(tmp_path: Path) -> None:
    before = DEFAULT_MANIFEST_PATH.read_bytes()

    def mutate(document: dict[str, Any]) -> None:
        for row in document["ci_divergences"]:
            if row["env_var"] == "PROBOS_LLM_URL":
                row["mechanism"] = "config-field-validator"

    try:
        errors = _check_with(_mutate_manifest(tmp_path, mutate)).errors
        assert any("but it is read from a model-validator" in error for error in errors)
    finally:
        _assert_committed_manifest_untouched(before)


# --------------------------------------------------------------------------
# 9. The smoke, and the three bindings that prove it still runs (D4).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supported_profile_boots_and_reads_a_file(tmp_path: Path) -> None:
    """CI boots the supported profile and does one real unit of work, offline.

    Named in ``docs/development/config-profiles.yaml`` as ``smoke_test_node_id``
    and resolved from there by AST, so renaming this function fails the gate.
    """
    target = tmp_path / "smoke.txt"
    target.write_text("hello from probos", encoding="utf-8")

    config = load_profile("supported")
    # Assert the profile is actually armed: an unarmed config would boot too,
    # and the smoke would then prove nothing about `supported`.
    assert config.approval_inbox.enabled is True
    assert config.security.memory.enforce_store is True

    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data")
    await runtime.start()
    try:
        results = await runtime.submit_intent(
            "read_file", params={"path": str(target)}, timeout=5.0
        )
        assert results
        assert all(result.success for result in results)
        assert {result.result for result in results} == {"hello from probos"}
    finally:
        await runtime.stop()
    assert not runtime._started


def test_the_manifest_names_this_module_as_the_smoke() -> None:
    document = yaml.safe_load(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert document["smoke_test_node_id"] == _SMOKE_NODE_ID


def test_the_smoke_resolves_by_ast_and_carries_no_skip_marker() -> None:
    errors: list[str] = []
    detail = checker._check_smoke_node(_SMOKE_NODE_ID, _REPO_ROOT, errors)
    assert errors == []
    assert detail["resolved"] is True
    assert detail["markers"] == []


@pytest.mark.parametrize("marker", ["skip", "skipif", "xfail"])
def test_a_skip_marker_on_the_smoke_would_fail(tmp_path: Path, marker: str) -> None:
    """A skipped smoke is a non-passing smoke, and skips hide in `passed`."""
    module = tmp_path / "tests"
    module.mkdir(parents=True, exist_ok=True)
    (module / "probe.py").write_text(
        f"import pytest\n\n\n@pytest.mark.{marker}\ndef test_boot():\n    pass\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    checker._check_smoke_node("tests/probe.py::test_boot", tmp_path, errors)
    assert any(marker in error for error in errors)


def test_the_selector_treats_the_loader_as_blast_radius() -> None:
    import fnmatch

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import select_tests

    patterns = select_tests.BLAST_RADIUS_PATTERNS
    assert any(
        fnmatch.fnmatch("src/probos/config_profiles.py", pattern)
        for pattern in patterns
    )
    assert any(
        fnmatch.fnmatch("config/profiles/supported.yaml", pattern)
        for pattern in patterns
    )
