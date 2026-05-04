"""AD-478 v1: WorkspaceOntologyRegistry tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.workspace_ontology import WorkspaceOntologyRegistry
from probos.config import SystemConfig
from probos.events import EventType
from probos.startup.finalize import _wire_workspace_ontology


def test_workspace_ontology_registry_initial_state() -> None:
    reg = WorkspaceOntologyRegistry()
    assert reg.term_count() == 0
    assert reg.top_terms() == ()
    assert reg.get_frequency("anything") == 0


def test_add_term_increments_frequency() -> None:
    reg = WorkspaceOntologyRegistry()
    reg.add_term("alpha")
    reg.add_term("alpha", frequency=2)
    assert reg.get_frequency("alpha") == 3
    assert reg.term_count() == 1


def test_add_term_empty_string_no_op() -> None:
    reg = WorkspaceOntologyRegistry()
    reg.add_term("")
    assert reg.term_count() == 0


def test_top_terms_returns_descending_order() -> None:
    reg = WorkspaceOntologyRegistry()
    reg.add_term("a", 1)
    reg.add_term("b", 5)
    reg.add_term("c", 3)
    assert reg.top_terms() == (("b", 5), ("c", 3), ("a", 1))


def test_top_terms_respects_k_limit() -> None:
    reg = WorkspaceOntologyRegistry()
    for term, freq in [("a", 1), ("b", 2), ("c", 3)]:
        reg.add_term(term, freq)
    assert reg.top_terms(k=2) == (("c", 3), ("b", 2))


def test_top_terms_k_zero_returns_empty() -> None:
    reg = WorkspaceOntologyRegistry()
    reg.add_term("a", 1)
    assert reg.top_terms(k=0) == ()
    assert reg.top_terms(k=-1) == ()


def test_max_terms_eviction_drops_lowest_frequency() -> None:
    reg = WorkspaceOntologyRegistry(max_terms=3)
    reg.add_term("alpha", 5)
    reg.add_term("beta", 1)  # lowest -- will be evicted
    reg.add_term("gamma", 10)
    reg.add_term("delta", 2)  # triggers eviction; beta drops
    assert reg.term_count() == 3
    assert reg.get_frequency("beta") == 0
    assert reg.get_frequency("alpha") == 5
    assert reg.get_frequency("gamma") == 10
    assert reg.get_frequency("delta") == 2


def test_add_term_emits_event_only_on_new_term_with_term_length() -> None:
    captured: list[tuple] = []

    def emit(event_type, payload):
        captured.append((event_type, payload))

    reg = WorkspaceOntologyRegistry(emit_event=emit)
    reg.add_term("hello")  # new -> emit
    reg.add_term("hello", frequency=3)  # increment -> no emit
    reg.add_term("world")  # new -> emit
    assert len(captured) == 2
    for event_type, payload in captured:
        assert event_type == EventType.WORKSPACE_TERM_REGISTERED
        # Privacy: term length only, never the term itself.
        assert "term" not in payload
        assert "term_length" in payload
        assert isinstance(payload["term_length"], int)
        assert "frequency" in payload
    assert captured[0][1]["term_length"] == len("hello")
    assert captured[1][1]["term_length"] == len("world")


# ---------- Wiring ------------------------------------------------------


def test_runtime_attribute_set_when_enabled() -> None:
    runtime = MagicMock()
    config = SystemConfig()
    assert config.workspace_ontology.enabled is True
    wired = _wire_workspace_ontology(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.workspace_ontology, WorkspaceOntologyRegistry)


def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = MagicMock()
    config = SystemConfig()
    config.workspace_ontology.enabled = False
    wired = _wire_workspace_ontology(runtime=runtime, config=config)
    assert wired is False
