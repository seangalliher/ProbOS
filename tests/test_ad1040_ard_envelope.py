"""AD-1040: ARD envelope data model + media-type taxonomy + config scaffold.

BF-287: every assertion uses REAL dataclasses / a REAL ``SystemConfig`` —
there is NO ``MagicMock`` anywhere in this module.
"""

import pytest

from probos.config import SystemConfig
from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    PROBOS_AXIS_TO_MEDIA_TYPE,
    AiCatalog,
    Attestation,
    CatalogEntry,
    HostInfo,
    ProvenanceLink,
    TrustManifest,
    build_urn,
    parse_urn,
    publisher_domain,
)


# --- DD-4: value-or-reference -------------------------------------------------


def test_catalog_entry_both_url_and_data_raises():
    with pytest.raises(ValueError):
        CatalogEntry(
            identifier="id",
            display_name="X",
            type="agent",
            url="https://example.com/a",
            data={"k": "v"},
        )


def test_catalog_entry_neither_url_nor_data_raises():
    with pytest.raises(ValueError):
        CatalogEntry(identifier="id", display_name="X", type="agent")


def test_catalog_entry_url_only_ok():
    entry = CatalogEntry(
        identifier="id", display_name="X", type="agent", url="https://example.com/a"
    )
    assert entry.url == "https://example.com/a"
    assert entry.data is None


def test_catalog_entry_data_only_ok():
    entry = CatalogEntry(
        identifier="id", display_name="X", type="agent", data={"k": "v"}
    )
    assert entry.data == {"k": "v"}
    assert entry.url is None


# --- DD-5: to_dict camelCase boundary + omit empty optionals ------------------


def test_catalog_entry_to_dict_has_camelcase_keys():
    entry = CatalogEntry(
        identifier="urn:air:probos.ai:skills:summarize",
        display_name="Summarize",
        type="skill",
        url="https://example.com/skill",
        representative_queries=["summarize this", "tl;dr"],
        trust_manifest=TrustManifest(identity="probos.ai"),
    )
    d = entry.to_dict()
    assert d["displayName"] == "Summarize"
    assert d["representativeQueries"] == ["summarize this", "tl;dr"]
    assert d["trustManifest"] == {"identity": "probos.ai"}
    # snake_case names must NOT leak through the boundary.
    assert "display_name" not in d
    assert "representative_queries" not in d
    assert "trust_manifest" not in d


def test_catalog_entry_to_dict_omits_empty_optionals():
    entry = CatalogEntry(
        identifier="id1", display_name="One", type="agent", url="https://e/x"
    )
    d = entry.to_dict()
    assert d == {
        "identifier": "id1",
        "displayName": "One",
        "type": "agent",
        "url": "https://e/x",
    }
    for omitted in (
        "data",
        "description",
        "tags",
        "capabilities",
        "representativeQueries",
        "version",
        "updatedAt",
        "metadata",
        "trustManifest",
    ):
        assert omitted not in d


def test_full_catalog_to_dict_round_trips_expected_shape():
    host = HostInfo(
        display_name="ProbOS",
        identifier="probos.ai",
        documentation_url="https://probos.ai/docs",
    )
    tool = CatalogEntry(
        identifier="urn:air:probos.ai:tools:read_file",
        display_name="Read File",
        type="built_in",
        url="https://probos.ai/tools/read_file",
    )
    skill = CatalogEntry(
        identifier="urn:air:probos.ai:skills:summarize",
        display_name="Summarize",
        type="skill",
        data={"instructions": "Summarize the input."},
        representative_queries=["summarize this"],
    )
    agent = CatalogEntry(
        identifier="urn:air:probos.ai:agents:researcher",
        display_name="Researcher",
        type="agent",
        url="https://probos.ai/agents/researcher",
        tags=["research"],
        trust_manifest=TrustManifest(
            identity="probos.ai",
            identity_type="domain",
            attestations=[
                Attestation(type="slsa", uri="https://e/att", digest="sha256:abc")
            ],
            provenance=[
                ProvenanceLink(
                    relation="derivedFrom", source_id="urn:air:probos.ai:agents:base"
                )
            ],
        ),
    )
    catalog = AiCatalog(host=host, entries=[tool, skill, agent])
    d = catalog.to_dict()

    assert d["specVersion"] == "1.0"
    assert d["host"]["displayName"] == "ProbOS"
    assert d["host"]["documentationUrl"] == "https://probos.ai/docs"
    assert len(d["entries"]) == 3
    # tool: url reference
    assert d["entries"][0]["url"] == "https://probos.ai/tools/read_file"
    assert "data" not in d["entries"][0]
    # skill: inline data + representativeQueries
    assert d["entries"][1]["data"] == {"instructions": "Summarize the input."}
    assert d["entries"][1]["representativeQueries"] == ["summarize this"]
    assert "url" not in d["entries"][1]
    # agent: tags + nested trustManifest (recursed, camelCase, omit-empty)
    assert d["entries"][2]["tags"] == ["research"]
    tm = d["entries"][2]["trustManifest"]
    assert tm["identity"] == "probos.ai"
    assert tm["identityType"] == "domain"
    assert tm["attestations"][0]["digest"] == "sha256:abc"
    assert tm["provenance"][0]["sourceId"] == "urn:air:probos.ai:agents:base"
    # ProvenanceLink omits the empty sourceDigest.
    assert "sourceDigest" not in tm["provenance"][0]


def test_ai_catalog_to_dict_omits_host_when_none():
    catalog = AiCatalog(entries=[])
    d = catalog.to_dict()
    assert d == {"specVersion": "1.0", "entries": []}
    assert "host" not in d


# --- DD-6: URN build / parse honest-degrade -----------------------------------


def test_build_then_parse_urn_round_trip():
    urn = build_urn("probos.ai", "agents", "researcher")
    assert urn == "urn:air:probos.ai:agents:researcher"
    assert parse_urn(urn) == ("probos.ai", "agents", "researcher")


def test_parse_urn_name_may_contain_colon():
    urn = build_urn("probos.ai", "tools", "ns:read:file")
    assert urn == "urn:air:probos.ai:tools:ns:read:file"
    assert parse_urn(urn) == ("probos.ai", "tools", "ns:read:file")


def test_publisher_domain_returns_fqdn():
    urn = build_urn("probos.ai", "agents", "researcher")
    assert publisher_domain(urn) == "probos.ai"


def test_parse_urn_malformed_returns_none():
    assert parse_urn("not-a-urn") is None
    assert parse_urn("") is None
    # Correct prefix but too few segments → still None (never raises).
    assert parse_urn("urn:air:onlythree") is None


def test_publisher_domain_malformed_returns_empty_string():
    assert publisher_domain("bad") == ""
    assert publisher_domain("") == ""


# --- media-type taxonomy ------------------------------------------------------


def test_probos_axis_to_media_type_mapping():
    assert PROBOS_AXIS_TO_MEDIA_TYPE["mcp"] == MT_MCP_SERVER
    assert PROBOS_AXIS_TO_MEDIA_TYPE["skill"] == MT_AI_SKILL
    assert PROBOS_AXIS_TO_MEDIA_TYPE["agent"] == MT_A2A_AGENT


# --- config: default-OFF scaffold ---------------------------------------------


def test_system_config_ard_default_off():
    cfg = SystemConfig()
    assert cfg.federation.ard.enabled is False
    assert cfg.federation.ard.well_known_path == "/.well-known/ai-catalog.json"
    assert cfg.federation.ard.discovery_endpoints == []
    assert cfg.federation.ard.registry_url == ""
    assert cfg.federation.ard.publisher_namespace_domain == ""


# --- DD-7: TrustManifest is a pure data carrier -------------------------------


def test_trust_manifest_is_pure_data_carrier():
    tm = TrustManifest(
        identity="probos.ai",
        identity_type="domain",
        attestations=[Attestation(type="slsa", uri="https://e/att")],
        provenance=[
            ProvenanceLink(relation="derivedFrom", source_id="urn:air:x:y:z")
        ],
    )
    # Constructed cleanly with real nested dataclasses.
    assert tm.identity == "probos.ai"
    assert tm.attestations[0].type == "slsa"
    assert tm.provenance[0].relation == "derivedFrom"
    # DD-7: no signing / verification surface, no key material.
    assert not hasattr(tm, "sign")
    assert not hasattr(tm, "verify")
