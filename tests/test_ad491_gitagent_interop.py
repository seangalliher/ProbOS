"""Tests for AD-491: gitagent interop adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from probos.interop.gitagent import (
    export_agent_to_gitagent_yaml,
    import_gitagent_yaml,
)


def _fake_agent(**overrides):
    cap_objs = overrides.pop(
        "default_capabilities",
        [SimpleNamespace(can="diagnose"), SimpleNamespace(can="report")],
    )
    intent_objs = overrides.pop(
        "intent_descriptors",
        [SimpleNamespace(name="diagnose"), SimpleNamespace(name="emit_report")],
    )
    base = dict(
        callsign="bones",
        agent_type="diagnostician",
        tier="domain",
        pool="medical",
        instructions="Diagnose system anomalies.",
        sovereign_id="abc123",
        did="did:probos:ship1:abc123",
        default_capabilities=cap_objs,
        intent_descriptors=intent_objs,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_export_minimal_agent_produces_valid_yaml():
    agent = _fake_agent()
    yaml_str = export_agent_to_gitagent_yaml(agent)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["name"] == "bones"
    assert parsed["runtime"] == "probos"
    assert parsed["agent_type"] == "diagnostician"
    assert parsed["tier"] == "domain"


def test_export_includes_probos_sovereign_id():
    agent = _fake_agent(sovereign_id="abc123")
    parsed = yaml.safe_load(export_agent_to_gitagent_yaml(agent))
    assert parsed["probos"]["sovereign_id"] == "abc123"


def test_export_handles_missing_sovereign_id_gracefully():
    agent = _fake_agent()
    # Strip sovereign_id attribute entirely
    delattr(agent, "sovereign_id")
    yaml_str = export_agent_to_gitagent_yaml(agent)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["probos"]["sovereign_id"] == ""


def test_export_capabilities_and_intents_serialize_as_lists():
    agent = _fake_agent(
        default_capabilities=[
            SimpleNamespace(can="a"),
            SimpleNamespace(can="b"),
            SimpleNamespace(can="c"),
        ],
        intent_descriptors=[
            SimpleNamespace(name="i1"),
            SimpleNamespace(name="i2"),
        ],
    )
    parsed = yaml.safe_load(export_agent_to_gitagent_yaml(agent))
    assert parsed["capabilities"] == ["a", "b", "c"]
    assert parsed["intents"] == ["i1", "i2"]


def test_import_round_trip_probos_runtime(tmp_path):
    agent = _fake_agent(sovereign_id="round-trip-id")
    yaml_str = export_agent_to_gitagent_yaml(agent)
    p = tmp_path / "agent.yaml"
    p.write_text(yaml_str, encoding="utf-8")
    parsed = import_gitagent_yaml(p)
    assert parsed["probos"]["sovereign_id"] == "round-trip-id"
    assert parsed["runtime"] == "probos"
    assert parsed["name"] == "bones"


def test_import_foreign_runtime_clears_sovereign_id(tmp_path):
    p = tmp_path / "foreign.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "intruder",
                "runtime": "gitagent",
                "probos": {
                    "sovereign_id": "forged-id",
                    "did": "did:probos:fake:forged",
                    "pool": "any",
                },
            }
        ),
        encoding="utf-8",
    )
    parsed = import_gitagent_yaml(p)
    assert parsed["probos"]["sovereign_id"] == ""
    assert parsed["probos"]["did"] == ""


def test_import_missing_required_key_raises_valueerror(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        yaml.safe_dump({"runtime": "probos"}),  # no 'name'
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="name"):
        import_gitagent_yaml(p)


def test_import_invalid_yaml_raises(tmp_path):
    p = tmp_path / "broken.yaml"
    p.write_text("name: [unterminated\n  bad: : :", encoding="utf-8")
    with pytest.raises((yaml.YAMLError, ValueError)):
        import_gitagent_yaml(p)
