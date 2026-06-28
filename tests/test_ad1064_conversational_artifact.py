"""AD-1064: teach crew agents to save a downloadable DOCUMENT in a 1:1 chat.

The Captain asked an agent to "save these recommendations in a document" and the
agent confabulated a ``[MESH create_file ...]`` write verb — the AD-869
``[MESH ...]`` seam is read-only and has no such verb, so nothing was saved. The
real, wired path is the AD-797 artifact extractor
(``DmReplyPipeline.step_4f_extract_artifacts``): an agent wraps the body in an
``<artifact name="..." mime="...">...</artifact>`` tag and the pipeline persists
it as a downloadable, versioned artifact + renders a clickable card. AD-1064 adds
the missing teaching hook ``CognitiveAgent._conversational_artifact_block`` so
every crew agent knows the real tag (honest-degraded on the artifact substrate),
mirroring the AD-912 notebook hook.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE


def _hook(runtime: object) -> str:
    """Call the base artifact hook with an arbitrary self carrying only a
    ``_runtime`` — exercises the generalized base behaviour for any crew agent."""
    return CognitiveAgent._conversational_artifact_block(
        SimpleNamespace(_runtime=runtime), {"intent": "direct_message"},
    )


def _runtime_with_stores() -> SimpleNamespace:
    return SimpleNamespace(artifact_store=object(), attachment_store=object())


def test_hook_teaches_real_artifact_tag_when_stores_wired() -> None:
    block = _hook(_runtime_with_stores())
    assert "<artifact" in block
    assert "</artifact>" in block
    assert 'mime="text/markdown"' in block
    assert "document" in block.lower()


def test_hook_honest_degrades_without_artifact_store() -> None:
    rt = SimpleNamespace(artifact_store=None, attachment_store=object())
    assert _hook(rt) == ""


def test_hook_honest_degrades_without_attachment_store() -> None:
    rt = SimpleNamespace(artifact_store=object(), attachment_store=None)
    assert _hook(rt) == ""


def test_hook_honest_degrades_without_runtime() -> None:
    assert _hook(None) == ""


def test_hook_no_runtime_attr_returns_empty() -> None:
    # An object with no ``_runtime`` at all (LSP safety) still degrades.
    assert CognitiveAgent._conversational_artifact_block(object(), {}) == ""


def test_hook_text_is_gap_regex_safe() -> None:
    block = _hook(_runtime_with_stores())
    assert not _CAPABILITY_GAP_RE.search(block)


def test_hook_does_not_teach_the_hallucinated_mesh_create_file() -> None:
    # The block must teach the REAL tag, never the fake verb the agent guessed.
    block = _hook(_runtime_with_stores())
    assert "create_file" not in block
    assert "[MESH" not in block
