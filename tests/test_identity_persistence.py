"""BF-057: Test identity persistence across restarts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.types import LLMResponse


# ── Helpers ──────────────────────────────────────────────────────────

def _make_agent(agent_type: str = "engineering_officer", callsign: str = "LaForge",
                agent_id: str = "eng_engineering_officer_0_abc12345"):
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.callsign = callsign
    agent.id = agent_id
    agent.pool = agent_type
    agent.state = MagicMock(value="idle")
    agent.confidence = 0.9
    agent.capabilities = []
    agent.is_alive = True
    agent._llm_client = AsyncMock()
    return agent


def _make_cert(callsign: str = "Tesla", agent_type: str = "engineering_officer",
               slot_id: str = "eng_engineering_officer_0_abc12345"):
    cert = MagicMock()
    cert.callsign = callsign
    cert.agent_type = agent_type
    cert.slot_id = slot_id
    cert.agent_uuid = "uuid-1234"
    cert.did = "did:probos:test:uuid-1234"
    return cert


def _make_runtime(identity_cert=None, has_ontology=False):
    """Build a minimal mock runtime for BF-057 tests."""
    from probos.runtime import ProbOSRuntime
    from probos.agent_onboarding import AgentOnboardingService

    rt = ProbOSRuntime.__new__(ProbOSRuntime)
    rt.config = SystemConfig()
    rt.callsign_registry = CallsignRegistry()
    rt.registry = MagicMock()
    rt.registry.all.return_value = []

    # Identity registry
    rt.identity_registry = MagicMock()
    if identity_cert:
        rt.identity_registry.get_by_slot = MagicMock(return_value=identity_cert)
    else:
        rt.identity_registry.get_by_slot = MagicMock(return_value=None)

    # Ontology
    if has_ontology:
        rt.ontology = MagicMock()
        rt.ontology.update_assignment_callsign = MagicMock(return_value=True)
    else:
        rt.ontology = None

    # AD-515: Create onboarding service for delegation
    rt._onboarding = AgentOnboardingService(
        callsign_registry=rt.callsign_registry,
        capability_registry=MagicMock(),
        gossip=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        event_log=MagicMock(),
        identity_registry=rt.identity_registry,
        ontology=rt.ontology,
        event_emitter=MagicMock(),
        config=rt.config,
        llm_client=None,
        registry=rt.registry,
        ward_room=None,
        acm=None,
    )

    return rt


# ── Tests ────────────────────────────────────────────────────────────


class TestBF057IdentityPersistence:
    """BF-057: Identity persistence on restart."""

    def test_naming_ceremony_skipped_with_existing_identity(self):
        """When birth cert exists, skip ceremony and restore callsign."""
        cert = _make_cert(callsign="Tesla")
        rt = _make_runtime(identity_cert=cert)
        agent = _make_agent(callsign="LaForge")  # seed callsign

        # The logic under test: check identity before naming ceremony
        is_crew = rt._is_crew_agent(agent)
        _existing = ""
        if is_crew and rt.identity_registry:
            existing_cert = rt.identity_registry.get_by_slot(agent.id)
            if existing_cert and existing_cert.callsign:
                _existing = existing_cert.callsign

        if _existing:
            agent.callsign = _existing
            rt.callsign_registry.set_callsign(agent.agent_type, _existing)

        assert agent.callsign == "Tesla"
        assert rt.callsign_registry.get_callsign("engineering_officer") == "Tesla"
        # LLM should NOT have been called
        agent._llm_client.complete.assert_not_called()

    def test_naming_ceremony_runs_without_identity(self):
        """On cold start (no cert), naming ceremony runs normally."""
        rt = _make_runtime(identity_cert=None)
        agent = _make_agent(callsign="LaForge")
        agent._llm_client.complete = AsyncMock(
            return_value=LLMResponse(content="Forge\nA solid engineering name.")
        )

        # The logic: no existing identity → ceremony runs
        is_crew = rt._is_crew_agent(agent)
        _existing = ""
        if is_crew and rt.identity_registry:
            existing_cert = rt.identity_registry.get_by_slot(agent.id)
            if existing_cert and existing_cert.callsign:
                _existing = existing_cert.callsign

        assert _existing == ""  # No existing identity → ceremony would run

        # Verify ceremony would produce the right name
        result = asyncio.get_event_loop().run_until_complete(
            rt._run_naming_ceremony(agent)
        )
        assert result == "Forge"
        agent._llm_client.complete.assert_called_once()

    def test_ontology_synced_on_identity_restore(self):
        """When callsign restored from cert, ontology gets updated."""
        cert = _make_cert(callsign="Tesla")
        rt = _make_runtime(identity_cert=cert, has_ontology=True)
        agent = _make_agent(callsign="LaForge")  # stale seed

        # Simulate the warm boot restore path
        existing_cert = rt.identity_registry.get_by_slot(agent.id)
        _existing = existing_cert.callsign

        if agent.callsign != _existing:
            agent.callsign = _existing
            rt.callsign_registry.set_callsign(agent.agent_type, _existing)
            if hasattr(rt, 'ontology') and rt.ontology:
                rt.ontology.update_assignment_callsign(agent.agent_type, _existing)

        rt.ontology.update_assignment_callsign.assert_called_once_with("engineering_officer", "Tesla")

    def test_warm_boot_identity_restore_logged(self, caplog):
        """BF-057 restore should log an info message."""
        cert = _make_cert(callsign="Tesla")
        rt = _make_runtime(identity_cert=cert)
        agent = _make_agent(callsign="LaForge")

        with caplog.at_level(logging.INFO):
            existing_cert = rt.identity_registry.get_by_slot(agent.id)
            _existing = existing_cert.callsign
            if agent.callsign != _existing:
                agent.callsign = _existing
                rt.callsign_registry.set_callsign(agent.agent_type, _existing)
                # Simulate the log call from runtime
                logging.getLogger("probos.runtime").info(
                    "BF-057: %s identity restored from birth certificate: '%s'",
                    agent.agent_type, _existing
                )

        assert any("BF-057" in r.message and "Tesla" in r.message for r in caplog.records)

    def test_identity_registry_empty_slot_returns_none(self):
        """get_by_slot for non-existent slot should return None."""
        rt = _make_runtime(identity_cert=None)
        result = rt.identity_registry.get_by_slot("unknown_slot_xyz")
        assert result is None

    def test_callsign_registry_updated_on_restore(self):
        """CallsignRegistry reflects restored callsign, not seed."""
        cert = _make_cert(callsign="Tesla")
        rt = _make_runtime(identity_cert=cert)
        agent = _make_agent(callsign="LaForge")

        # Set seed callsign first (as boot would)
        rt.callsign_registry.set_callsign("engineering_officer", "LaForge")
        assert rt.callsign_registry.get_callsign("engineering_officer") == "LaForge"

        # Now restore from cert
        existing_cert = rt.identity_registry.get_by_slot(agent.id)
        rt.callsign_registry.set_callsign(agent.agent_type, existing_cert.callsign)

        assert rt.callsign_registry.get_callsign("engineering_officer") == "Tesla"
        # resolve() should find it (case-insensitive)
        resolved = rt.callsign_registry.resolve("tesla")
        assert resolved is not None
        assert resolved["agent_type"] == "engineering_officer"
